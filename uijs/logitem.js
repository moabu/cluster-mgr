import {Component} from 'react';

const StateIcon = (props) => {
    const {state} = props;
    if (state === 'running') {
        return <i className="glyphicon glyphicon-flash text-warning" />;
    }
    else if (state === 'fail') {
        return <i className="glyphicon glyphicon-remove-circle text-danger" />;
    }
    else if (state === 'success') {
        return <i className="glyphicon glyphicon-ok-circle text-success" />;
    }
    else if (state === 'complete') {
        return <i className="glyphicon glyphicon-ok text-info" />;
    }
    return state;
};


class LogItem extends Component {
    constructor (props) {
        super(props);
        this.state = {
            outputShown: true,
        };
        this.toggleOutput = this.toggleOutput.bind(this);
    }

    toggleOutput() {
        this.setState(prevState => ({
            outputShown: !prevState.outputShown,
        }));
    };

    componentWillUpdate(prevProps){
        if (prevProps.state !== this.props.state) {
            this.setState({outputShown: false});
        }
    }

    render (){
        return (
            <div id={"logItem_" + this.props.id} className="log-item">
                <div className="row">
                    <div className="col-md-10">
                        <p className={"command command-" + this.props.state}>
                            <StateIcon state={this.props.state}/>
                            <span className="host"> root@{this.props.server}:~# </span>{this.props.action}
                        </p>
                    </div>
                    <div className="col-md-2" onClick={this.toggleOutput}>
                        { this.state.outputShown
                            ? <span className="label label-default" style={{cursor: "pointer"}}>hide log</span>
                            : <span className="label label-default" style={{cursor: "pointer"}}>show log</span>
                        }
                    </div>
                </div>

                <pre id={"pre_"+this.props.id} className={this.state.outputShown ? "": "hidden"}>{this.props.output}</pre>
            </div>
        );
    }
}

export default LogItem
