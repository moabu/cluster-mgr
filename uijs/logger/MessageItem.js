import React, {Component} from 'react';

const MsgIcon = (props) => {
    switch (props.level) {
        case "info": return <i className="glyphicon glyphicon-info-sign" />;
        case "success": return <i className="glyphicon glyphicon-ok-sign" />;
        case "warning": return <i className="glyphicon glyphicon-warning-sign" />;
        case "danger":
        case "error":
        case "fail": return <i className="glyphicon glyphicon-remove-sign" />
        default: return <i className="glyphicon glyphicon-ok" />
    }
};

const Msg = (props) => {
    return (
        <p className={"msg msg-"+props.level}>
            <MsgIcon level={props.level} /> {"  "+props.msg}
        </p>
    );
};


class MessageItem extends Component{
    constructor (props){
        super(props);
    }


    render(){
        let message = null;
        if (this.props.level === "debug"){
            message = <pre>{this.props.msg}</pre>;
        } else {
            message = <Msg level={this.props.level} msg={this.props.msg} />
        }
        return (
            <div className="log-item">
                {message}
            </div>
        );
    }
}

export default MessageItem