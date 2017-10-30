import {Component} from 'react';

const MsgIcon = (level) => {
    switch (level) {
        case "info": return <i className="glyphicon glyphicon-info-sign" />;
        case "success": return <i className="glyphicon glyphicon-ok-sign" />;
        case "warning": return <i className="glyphicon glyphicon-warning-sign" />;
        case "danger":
        case "error":
        case "fail": return <i className="glyphicon glyphicon-remove-sign" />
    }
};

class MessageItem extends Component{
    constructor (props){
        super(props);
    }

    render(){
        return (
            <div className="log-item">
                <p className={"msg msg-"+this.props.level}>
                    <MsgIcon level={this.props.level} />
                     {this.props.msg}
                </p>
            </div>
        );
    }
}

export default MessageItem